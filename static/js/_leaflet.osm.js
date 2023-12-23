import { FeatureGroup, TileLayer, Util, circleMarker, latLng, latLngBounds, polygon, polyline, rectangle } from 'leaflet'

const defaultLayer = TileLayer.extend({
    options: {
        url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors'
    },

    initialize: options => {
        options = Util.setOptions(this, options)
        TileLayer.prototype.initialize.call(this, options.url)
    }
})

export const Mapnik = defaultLayer.extend({
    options: {
        url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        maxZoom: 19
    }
})

export const CyclOSM = defaultLayer.extend({
    options: {
        url: 'https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png',
        maxZoom: 20,
        subdomains: 'abc',
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors. Tiles courtesy of <a href="https://www.openstreetmap.fr" target="_blank">OpenStreetMap France</a>'
    }
})

export const CycleMap = defaultLayer.extend({
    options: {
        url: 'https://{s}.tile.thunderforest.com/cycle/{z}/{x}/{y}{r}.png?apikey={apikey}',
        maxZoom: 21,
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors. Tiles courtesy of <a href="http://www.thunderforest.com/" target="_blank">Andy Allan</a>'
    }
})

export const TransportMap = defaultLayer.extend({
    options: {
        url: 'https://{s}.tile.thunderforest.com/transport/{z}/{x}/{y}{r}.png?apikey={apikey}',
        maxZoom: 21,
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors. Tiles courtesy of <a href="http://www.thunderforest.com/" target="_blank">Andy Allan</a>'
    }
})

export const OPNVKarte = defaultLayer.extend({
    options: {
        url: 'https://tileserver.memomaps.de/tilegen/{z}/{x}/{y}.png',
        maxZoom: 18,
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors. Tiles courtesy of <a href="http://memomaps.de/" target="_blank">MeMoMaps</a>'
    }
})

export const HOT = defaultLayer.extend({
    options: {
        url: 'https://tile-{s}.openstreetmap.fr/hot/{z}/{x}/{y}.png',
        maxZoom: 20,
        subdomains: 'abc',
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors. Tiles courtesy of <a href="http://hot.openstreetmap.org/" target="_blank">Humanitarian OpenStreetMap Team</a>'
    }
})

export const TracestrackTopo = defaultLayer.extend({
    options: {
        url: 'https://tile.tracestrack.com/topo__/{z}/{x}/{y}.png?key={apikey}',
        maxZoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors. Tiles courtesy of <a href="https://www.tracestrack.com/" target="_blank">Tracestrack Maps</a>'
    }
})

export const GPS = defaultLayer.extend({
    options: {
        url: 'https://gps.tile.openstreetmap.org/lines/{z}/{x}/{y}.png',
        maxZoom: 21,
        maxNativeZoom: 20,
        subdomains: 'abc'
    }
})

export const DataLayer = FeatureGroup.extend({
    options: {
        areaTags: ['area', 'building', 'leisure', 'tourism', 'ruins', 'historic', 'landuse', 'military', 'natural', 'sport'],
        styles: {}
    },

    initialize: (xml, options) => {
        Util.setOptions(this, options)
        FeatureGroup.prototype.initialize.call(this)

        if (xml)
            this.addData(xml)
    },

    addData: features => {
        if (!Array.isArray(features))
            features = this.buildFeatures(features)

        features.forEach(feature => {
            let layer

            switch (feature.type) {
                case "changeset":
                    layer = rectangle(feature.latLngBounds, this.options.styles.changeset)
                    break
                case "node":
                    layer = circleMarker(feature.latLng, this.options.styles.node)
                    break
                default:
                    const latLngs = feature.nodes.map(node => node.latLng)
                    if (this.isWayArea(feature)) {
                        latLngs.pop() // remove last == first
                        layer = polygon(latLngs, this.options.styles.area)
                    } else {
                        layer = polyline(latLngs, this.options.styles.way)
                    }
                    break
            }

            layer.addTo(this)
            layer.feature = feature
        })
    },

    buildFeatures: xml => {
        const changesets = getChangesets(xml)
        const nodes = getNodes(xml)
        const ways = getWays(xml, nodes)
        const relations = getRelations(xml, nodes, ways)

        const interestingNodes = Object.values(nodes).filter(node => this.interestingNode(node, ways, relations))
        const features = [...changesets, ...ways, ...interestingNodes]
        return features
    },

    isWayArea: way => {
        if (way.nodes.length <= 2)
            return false

        const isClosedWay = way.nodes[0] === way.nodes[way.nodes.length - 1]
        if (!isClosedWay)
            return false

        const hasAreaTag = Object.keys(way.tags).some(key => this.options.areaTags.includes(key))
        return hasAreaTag
    },

    interestingNode: (node, ways, relations) => {
        const usedInWay = ways.some(way => way.nodes.includes(node))
        if (!usedInWay) return true

        const usedInRelation = relations.some(relation => relation.members.includes(node))
        if (!usedInRelation) return true

        const hasTags = Object.keys(node.tags).length > 0
        return hasTags
    }
})

const getChangesets = xml => {
    const nodes = Array.from(xml.getElementsByTagName("changeset"))
    return nodes.map(node => ({
        id: node.getAttribute("id"),
        type: "changeset",
        latLngBounds: latLngBounds(
            [node.getAttribute("min_lat"), node.getAttribute("min_lon")],
            [node.getAttribute("max_lat"), node.getAttribute("max_lon")]),
        tags: this.getTags(node)
    }))
}

const getNodes = xml => {
    const nodes = Array.from(xml.getElementsByTagName("node"))
    return nodes.reduce((result, node) => {
        const id = node.getAttribute("id")
        result[id] = {
            id: id,
            type: "node",
            latLng: latLng(
                node.getAttribute("lat"),
                node.getAttribute("lon")),
            tags: this.getTags(node)
        }
        return result
    }, {})
}

const getWays = (xml, nodes) => {
    const ways = Array.from(xml.getElementsByTagName("way"))
    return ways.map(way => {
        const nodesIds = Array.from(way.getElementsByTagName("nd"))
        const nodesArray = nodesIds.map(nd => nodes[nd.getAttribute("ref")])

        return {
            id: way.getAttribute("id"),
            type: "way",
            nodes: nodesArray,
            tags: this.getTags(way)
        }
    })
}

const getRelations = (xml, nodes, ways) => {
    const rels = Array.from(xml.getElementsByTagName("relation"))
    return rels.map(rel => {
        const members = Array.from(rel.getElementsByTagName("member"))

        return {
            id: rel.getAttribute("id"),
            type: "relation",
            members: members.map(member => {
                if (member.getAttribute("type") === "node")
                    return nodes[member.getAttribute("ref")]
                else
                    // relation-way and relation-relation membership not implemented
                    // it is not currently needed and would decrease performance
                    return null
            }),
            tags: this.getTags(rel)
        }
    })
}

const getTags = xml => {
    const tags = Array.from(xml.getElementsByTagName("tag"))
    return tags.reduce((result, tag) => {
        result[tag.getAttribute("k")] = tag.getAttribute("v")
        return result
    }, {})
}
